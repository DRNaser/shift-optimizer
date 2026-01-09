# =============================================================================
# SOLVEREIGN Routing Pack - OSRM Map Hash Computation (Audit-Safe)
# =============================================================================
# Computes SHA256 hash of mounted OSRM map files for evidence/audit.
#
# KEY PROPERTIES:
# - Path-neutral: Hash is computed from file CONTENT only, not paths
# - Deterministic: Same map content = same hash across deployments
# - Fail-closed: Missing required files = MISSING_REQUIRED status (not OK)
# - UTC timestamps: All timestamps are timezone-aware UTC
#
# Usage:
#   from backend_py.packs.routing.services.finalize.osrm_map_hash import (
#       compute_osrm_map_hash,
#       OSRMMapInfo,
#       OSRMMapStatus,
#   )
#
#   info = compute_osrm_map_hash("/data/osrm/austria-latest.osrm")
#   if info.status == OSRMMapStatus.OK:
#       print(f"Map hash: sha256:{info.map_hash}")
#   else:
#       print(f"Map error: {info.status}")
# =============================================================================

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class OSRMMapStatus(str, Enum):
    """Status of OSRM map hash computation."""
    OK = "OK"                           # All files present, hash computed
    NOT_FOUND = "NOT_FOUND"             # No OSRM files found at path
    MISSING_REQUIRED = "MISSING_REQUIRED"  # Required files missing
    NOT_CONFIGURED = "NOT_CONFIGURED"   # No path configured
    DOCKER_ERROR = "DOCKER_ERROR"       # Docker exec failed
    TIMEOUT = "TIMEOUT"                 # Hash computation timed out
    ERROR = "ERROR"                     # Generic error


class HashScope(str, Enum):
    """Scope of what was hashed."""
    FULL_SET = "FULL_SET"               # All OSRM files
    REQUIRED_ONLY = "REQUIRED_ONLY"     # Only required files
    MAIN_FILE = "MAIN_FILE"             # Only the main .osrm file


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class OSRMMapInfo:
    """
    Information about an OSRM map file set.

    IMPORTANT: map_hash is only valid when status == OK.
    Never use map_hash without checking status first.
    """

    # Status of the computation
    status: OSRMMapStatus

    # Hash of the map (SHA256) - ONLY valid when status == OK
    map_hash: Optional[str] = None

    # Hash algorithm used
    hash_algorithm: str = "SHA256"

    # Scope of what was hashed
    hash_scope: HashScope = HashScope.FULL_SET

    # Base path (for reference only, NOT included in hash)
    base_path: str = ""

    # Files included in hash (filenames only, not paths)
    files_hashed: List[str] = field(default_factory=list)

    # Total size of all files
    total_size_bytes: int = 0

    # Modification time of newest file (UTC)
    newest_mtime: Optional[datetime] = None

    # OSRM profile (car, foot, etc.)
    profile: str = "car"

    # Computed at (UTC)
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Error message if status != OK
    error_message: Optional[str] = None

    # Missing files (for MISSING_REQUIRED status)
    missing_files: List[str] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        """Check if hash computation succeeded."""
        return self.status == OSRMMapStatus.OK

    @property
    def is_usable(self) -> bool:
        """Check if the map info is usable for routing."""
        return self.status == OSRMMapStatus.OK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "map_hash": self.map_hash,
            "hash_algorithm": self.hash_algorithm,
            "hash_scope": self.hash_scope.value,
            "base_path": self.base_path,
            "files_hashed": self.files_hashed,
            "total_size_bytes": self.total_size_bytes,
            "newest_mtime": self.newest_mtime.isoformat() if self.newest_mtime else None,
            "profile": self.profile,
            "computed_at": self.computed_at.isoformat(),
            "error_message": self.error_message,
            "missing_files": self.missing_files if self.missing_files else None,
        }

    def to_evidence_dict(self) -> Dict[str, Any]:
        """Format for routing evidence storage."""
        return {
            "osrm_map": {
                "status": self.status.value,
                "hash": self.map_hash,
                "hash_algorithm": self.hash_algorithm,
                "hash_scope": self.hash_scope.value,
                "profile": self.profile,
                "files_hashed": self.files_hashed,
                "total_size_bytes": self.total_size_bytes,
                "newest_mtime": self.newest_mtime.isoformat() if self.newest_mtime else None,
                "computed_at": self.computed_at.isoformat(),
            }
        }


# =============================================================================
# OSRM MAP EXTENSIONS
# =============================================================================

# Standard OSRM file extensions for a complete map
OSRM_EXTENSIONS = [
    ".osrm",              # Core graph
    ".osrm.ebg",          # Edge-based graph
    ".osrm.ebg_nodes",    # EBG nodes
    ".osrm.edges",        # Edge data
    ".osrm.enw",          # Edge node weights
    ".osrm.fileIndex",    # File index
    ".osrm.geometry",     # Geometry data
    ".osrm.icd",          # Turn penalty index
    ".osrm.maneuver_overrides",  # Maneuver overrides
    ".osrm.mldgr",        # MLD graph
    ".osrm.names",        # Street names
    ".osrm.nbg_nodes",    # NBG nodes
    ".osrm.partition",    # MLD partition
    ".osrm.properties",   # Properties
    ".osrm.ramIndex",     # RAM index
    ".osrm.restrictions", # Turn restrictions
    ".osrm.timestamp",    # Build timestamp
    ".osrm.tld",          # Turn lane data
    ".osrm.tls",          # Traffic lights
    ".osrm.turn_duration_penalties",  # Turn penalties
    ".osrm.turn_penalties_index",     # Turn penalty index
    ".osrm.turn_weight_penalties",    # Weight penalties
]

# Minimum required extensions for a valid OSRM map
OSRM_REQUIRED_EXTENSIONS = [
    ".osrm",
    ".osrm.names",
    ".osrm.properties",
]


# =============================================================================
# HASH COMPUTATION
# =============================================================================

def compute_osrm_map_hash(
    base_path: str,
    profile: str = "car",
    include_all: bool = True,
    require_all_required: bool = True,
) -> OSRMMapInfo:
    """
    Compute SHA256 hash of OSRM map files.

    IMPORTANT: Hash is path-neutral - only file CONTENT is hashed.
    Files are identified by their extension (e.g., ".osrm.names") not full path.
    This ensures same map content produces same hash across different mount points.

    Args:
        base_path: Base path to OSRM files (without extension)
                   e.g., "/data/osrm/austria-latest.osrm" or "/data/osrm/austria-latest"
        profile: OSRM profile name (for metadata)
        include_all: If True, hash all OSRM files; if False, only required files
        require_all_required: If True, return MISSING_REQUIRED when required files missing

    Returns:
        OSRMMapInfo with status and hash (if successful)

    Example:
        info = compute_osrm_map_hash("/data/osrm/austria-latest")
        if info.is_ok:
            print(f"Hash: sha256:{info.map_hash}")
        else:
            print(f"Error: {info.status} - {info.error_message}")
    """
    computed_at = datetime.now(timezone.utc)

    # Normalize base path (remove .osrm if present)
    base = str(base_path)
    if base.endswith(".osrm"):
        base = base[:-5]

    # Determine which extensions to hash
    extensions = OSRM_EXTENSIONS if include_all else OSRM_REQUIRED_EXTENSIONS
    hash_scope = HashScope.FULL_SET if include_all else HashScope.REQUIRED_ONLY

    # Find existing files
    files_to_hash = []
    total_size = 0
    newest_mtime = None

    for ext in extensions:
        file_path = Path(f"{base}{ext}")
        if file_path.exists():
            files_to_hash.append((ext, file_path))
            stat = file_path.stat()
            total_size += stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime

    # Check for no files found
    if not files_to_hash:
        logger.warning(f"No OSRM files found at base path: {base}")
        return OSRMMapInfo(
            status=OSRMMapStatus.NOT_FOUND,
            map_hash=None,
            hash_scope=hash_scope,
            base_path=base,
            files_hashed=[],
            total_size_bytes=0,
            profile=profile,
            computed_at=computed_at,
            error_message=f"No OSRM files found at {base}",
        )

    # Check for required files (fail-closed)
    if require_all_required:
        missing_required = []
        found_extensions = {ext for ext, _ in files_to_hash}
        for ext in OSRM_REQUIRED_EXTENSIONS:
            if ext not in found_extensions:
                missing_required.append(ext)

        if missing_required:
            logger.error(f"Missing required OSRM files: {missing_required}")
            return OSRMMapInfo(
                status=OSRMMapStatus.MISSING_REQUIRED,
                map_hash=None,
                hash_scope=hash_scope,
                base_path=base,
                files_hashed=[ext for ext, _ in files_to_hash],
                total_size_bytes=total_size,
                newest_mtime=newest_mtime,
                profile=profile,
                computed_at=computed_at,
                error_message=f"Missing required files: {', '.join(missing_required)}",
                missing_files=missing_required,
            )

    # Compute combined hash (PATH-NEUTRAL)
    combined_hash = hashlib.sha256()

    # Sort by extension for deterministic ordering
    files_to_hash.sort(key=lambda x: x[0])

    for ext, file_path in files_to_hash:
        # Hash ONLY the extension (not the full path) for path-neutrality
        # This ensures same content at different paths produces same hash
        combined_hash.update(ext.encode('utf-8'))

        # Hash file content
        try:
            with open(file_path, 'rb') as f:
                # Read in chunks for large files
                for chunk in iter(lambda: f.read(65536), b''):
                    combined_hash.update(chunk)
        except IOError as e:
            logger.error(f"Error reading {file_path}: {e}")
            return OSRMMapInfo(
                status=OSRMMapStatus.ERROR,
                map_hash=None,
                hash_scope=hash_scope,
                base_path=base,
                files_hashed=[ext for ext, _ in files_to_hash],
                total_size_bytes=total_size,
                newest_mtime=newest_mtime,
                profile=profile,
                computed_at=computed_at,
                error_message=f"Error reading file: {e}",
            )

    return OSRMMapInfo(
        status=OSRMMapStatus.OK,
        map_hash=combined_hash.hexdigest(),
        hash_algorithm="SHA256",
        hash_scope=hash_scope,
        base_path=base,
        files_hashed=[ext for ext, _ in files_to_hash],
        total_size_bytes=total_size,
        newest_mtime=newest_mtime,
        profile=profile,
        computed_at=computed_at,
    )


def compute_osrm_map_hash_from_docker(
    container_name: str = "solvereign-osrm",
    map_path: str = "/data/austria-latest.osrm",
    profile: str = "car",
) -> OSRMMapInfo:
    """
    Compute OSRM map hash from a Docker container.

    WARNING: This method only hashes the MAIN .osrm file, not the full set.
    The hash_scope will be MAIN_FILE. For full set hashing, use
    compute_osrm_map_hash() on mounted files.

    Args:
        container_name: Name of the OSRM Docker container
        map_path: Path to map inside container
        profile: OSRM profile name

    Returns:
        OSRMMapInfo with hash_scope=MAIN_FILE
    """
    import subprocess

    computed_at = datetime.now(timezone.utc)

    try:
        # Compute hash inside container
        # Use sha256sum on the main .osrm file
        result = subprocess.run(
            [
                "docker", "exec", container_name,
                "sha256sum", map_path
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            # Parse sha256sum output: "hash  filename"
            hash_value = result.stdout.strip().split()[0]
            return OSRMMapInfo(
                status=OSRMMapStatus.OK,
                map_hash=hash_value,
                hash_algorithm="SHA256",
                hash_scope=HashScope.MAIN_FILE,  # Important: only main file
                base_path=map_path,
                files_hashed=[Path(map_path).name],
                profile=profile,
                computed_at=computed_at,
            )
        else:
            logger.error(f"Failed to compute hash in container: {result.stderr}")
            return OSRMMapInfo(
                status=OSRMMapStatus.DOCKER_ERROR,
                map_hash=None,
                hash_scope=HashScope.MAIN_FILE,
                base_path=map_path,
                profile=profile,
                computed_at=computed_at,
                error_message=f"Docker exec failed: {result.stderr[:200]}",
            )

    except subprocess.TimeoutExpired:
        logger.error("Timeout computing hash in Docker container")
        return OSRMMapInfo(
            status=OSRMMapStatus.TIMEOUT,
            map_hash=None,
            hash_scope=HashScope.MAIN_FILE,
            base_path=map_path,
            profile=profile,
            computed_at=computed_at,
            error_message="Hash computation timed out (60s)",
        )
    except FileNotFoundError:
        logger.error("Docker command not found")
        return OSRMMapInfo(
            status=OSRMMapStatus.ERROR,
            map_hash=None,
            hash_scope=HashScope.MAIN_FILE,
            base_path=map_path,
            profile=profile,
            computed_at=computed_at,
            error_message="Docker command not found",
        )
    except Exception as e:
        logger.error(f"Error computing hash from Docker: {e}")
        return OSRMMapInfo(
            status=OSRMMapStatus.ERROR,
            map_hash=None,
            hash_scope=HashScope.MAIN_FILE,
            base_path=map_path,
            profile=profile,
            computed_at=computed_at,
            error_message=str(e)[:200],
        )


def get_osrm_map_hash_from_env() -> OSRMMapInfo:
    """
    Get OSRM map hash from environment variable or compute it.

    Checks in order:
    1. SOLVEREIGN_OSRM_MAP_HASH env var (pre-computed)
    2. SOLVEREIGN_OSRM_MAP_PATH env var (compute hash)
    3. Default path /data/osrm/austria-latest

    Environment variables:
    - SOLVEREIGN_OSRM_MAP_HASH: Pre-computed SHA256 hash
    - SOLVEREIGN_OSRM_MAP_PATH: Path to OSRM files (will compute hash)
    - SOLVEREIGN_OSRM_PROFILE: Profile name (default: "car")

    Returns:
        OSRMMapInfo with hash and status
    """
    computed_at = datetime.now(timezone.utc)

    # Get profile from env (used for all paths)
    profile = os.environ.get("SOLVEREIGN_OSRM_PROFILE", "car")

    # Check for pre-computed hash
    env_hash = os.environ.get("SOLVEREIGN_OSRM_MAP_HASH")
    if env_hash:
        map_path = os.environ.get("SOLVEREIGN_OSRM_MAP_PATH", "env:pre-computed")
        return OSRMMapInfo(
            status=OSRMMapStatus.OK,
            map_hash=env_hash,
            hash_algorithm="SHA256",
            hash_scope=HashScope.FULL_SET,  # Assume full set for pre-computed
            base_path=map_path,
            profile=profile,
            computed_at=computed_at,
        )

    # Check for map path
    map_path = os.environ.get("SOLVEREIGN_OSRM_MAP_PATH")
    if map_path:
        return compute_osrm_map_hash(map_path, profile=profile)

    # Try default path
    default_path = "/data/osrm/austria-latest"
    if Path(f"{default_path}.osrm").exists():
        return compute_osrm_map_hash(default_path, profile=profile)

    # Not configured
    return OSRMMapInfo(
        status=OSRMMapStatus.NOT_CONFIGURED,
        map_hash=None,
        base_path="",
        profile=profile,
        computed_at=computed_at,
        error_message="No OSRM map path configured (set SOLVEREIGN_OSRM_MAP_PATH)",
    )


def check_osrm_map_usable(info: OSRMMapInfo, allow_degraded: bool = False) -> tuple:
    """
    Check if OSRM map is usable for routing.

    Args:
        info: OSRMMapInfo from hash computation
        allow_degraded: If True, allow NOT_CONFIGURED status (degraded mode)

    Returns:
        (is_usable: bool, block_reason: Optional[str])
    """
    if info.status == OSRMMapStatus.OK:
        return (True, None)

    if info.status == OSRMMapStatus.NOT_CONFIGURED and allow_degraded:
        return (True, None)  # Degraded mode allowed

    # All other statuses are blocking
    block_reasons = {
        OSRMMapStatus.NOT_FOUND: f"OSRM map not found at {info.base_path}",
        OSRMMapStatus.MISSING_REQUIRED: f"Missing required files: {info.missing_files}",
        OSRMMapStatus.NOT_CONFIGURED: "OSRM map path not configured",
        OSRMMapStatus.DOCKER_ERROR: f"Docker error: {info.error_message}",
        OSRMMapStatus.TIMEOUT: "OSRM hash computation timed out",
        OSRMMapStatus.ERROR: f"Error: {info.error_message}",
    }

    return (False, block_reasons.get(info.status, f"Unknown status: {info.status}"))
